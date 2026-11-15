import test from "node:test";
import assert from "node:assert/strict";
import { demoGroups, displayName, describe } from "../src/demoAccounts.js";

const account = (username, role, account_type = "home", extra = {}) => ({
  username,
  role,
  account_type,
  sites: [],
  areas: [],
  crews: [],
  ...extra,
});

test("demo accounts are grouped customers first, then operations by role", () => {
  const groups = demoGroups([
    account("ana", "technician", "home", { crews: ["Battery service"] }),
    account("albert", "customer", "business", { sites: ["F1"] }),
    account("andrei", "dispatcher"),
    account("elena", "supervisor"),
    account("maria", "customer"),
  ]);
  assert.deepEqual(groups.map((g) => g.title), ["Customers", "PPC operations"]);
  assert.deepEqual(groups[0].accounts.map((a) => a.username), ["albert", "maria"]);
  assert.deepEqual(
    groups[1].accounts.map((a) => a.role),
    ["supervisor", "dispatcher", "technician"],
  );
  assert.equal(groups[0].accounts[0].label, "Business customer");
});

test("names and descriptions are readable", () => {
  assert.equal(displayName("laundry-owner"), "Laundry Owner");
  assert.match(describe(account("x", "supervisor")), /cannot apply/);
  assert.match(
    describe(account("y", "customer", "business", { sites: ["F1"] })),
    /Business account · Sites: F1/,
  );
});
