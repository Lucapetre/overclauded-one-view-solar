// Pure presentation of demo accounts for the landing page.
const ROLE_LABEL = {
  customer: "Customer",
  dispatcher: "PPC dispatcher",
  supervisor: "PPC manager",
  technician: "Technician",
};
const ROLE_ORDER = ["customer", "supervisor", "dispatcher", "technician"];

export const displayName = (username) =>
  username
    .split(/[-_.]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

export function describe(account) {
  const parts = [];
  if (account.role === "customer")
    parts.push(account.account_type === "business" ? "Business account" : "Home account");
  if (account.sites.length) parts.push(`Sites: ${account.sites.join(", ")}`);
  if (account.areas.length) parts.push(`Areas: ${account.areas.join(", ")}`);
  if (account.crews.length) parts.push(`Crew: ${account.crews.join(", ")}`);
  if (account.role === "supervisor")
    parts.push("Views plans and reports; cannot apply crew plans");
  if (account.role === "dispatcher") parts.push("Ranks incidents and applies crew plans");
  return parts.join(" · ");
}

export function demoGroups(accounts) {
  const groups = [
    { title: "Customers", roles: ["customer"] },
    { title: "PPC operations", roles: ["supervisor", "dispatcher", "technician"] },
  ];
  return groups
    .map((group) => ({
      title: group.title,
      accounts: accounts
        .filter((account) => group.roles.includes(account.role))
        .sort(
          (a, b) =>
            ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role) ||
            a.username.localeCompare(b.username),
        )
        .map((account) => ({
          ...account,
          name: displayName(account.username),
          label:
            account.role === "customer" && account.account_type === "business"
              ? "Business customer"
              : account.role === "supervisor" && account.areas.length === 1
                ? "Area manager"
                : ROLE_LABEL[account.role] || account.role,
          description: describe(account),
        })),
    }))
    .filter((group) => group.accounts.length);
}
