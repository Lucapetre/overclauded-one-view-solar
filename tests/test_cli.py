import pytest

from backend.__main__ import main
from backend.errors import ApiError
from backend.provisioning import create_user
from backend.security import verify_password


@pytest.fixture
def cli_database(database, monkeypatch):
    monkeypatch.setenv("SOLAR_DATABASE", str(database.path))
    monkeypatch.delenv("SOLAR_ACCOUNT_PASSWORD", raising=False)
    return database


def test_existing_account_is_checked_before_password_policy(database):
    with pytest.raises(ApiError) as error:
        create_user(database, "customer", "short", "customer")
    assert error.value.code == "account_exists"


def test_existing_account_does_not_prompt(cli_database, monkeypatch, capsys):
    def unexpected_prompt(_):
        pytest.fail("An existing account should not prompt for a new password")

    monkeypatch.setattr("backend.__main__.getpass.getpass", unexpected_prompt)
    with pytest.raises(SystemExit) as error:
        main(["create-user", "customer", "--role", "customer"])
    assert error.value.code == 2
    output = capsys.readouterr().err
    assert "already exists" in output
    assert "set-password" in output
    assert str(cli_database.path) in output
    assert "Traceback" not in output


@pytest.mark.parametrize("password", ["short", "x" * 257])
def test_invalid_password_has_actionable_error(
    cli_database, monkeypatch, capsys, password
):
    monkeypatch.setattr("backend.__main__.getpass.getpass", lambda _: password)
    with pytest.raises(SystemExit) as error:
        main(["create-user", "new-customer", "--role", "customer"])
    assert error.value.code == 2
    output = capsys.readouterr().err
    assert "Password must be 12" in output
    assert "Traceback" not in output
    assert password not in output


def test_missing_grant_user_has_a_clean_error(cli_database, capsys):
    with pytest.raises(SystemExit) as error:
        main(["grant-site", "unknown-user", "north-01"])
    assert error.value.code == 2
    output = capsys.readouterr().err
    assert "User not found" in output
    assert "create-user" in output
    assert "Traceback" not in output


def test_repeating_a_grant_succeeds(cli_database, capsys):
    main(["grant-site", "customer", "north-01"])
    main(["grant-site", "customer", "north-01"])
    assert capsys.readouterr().out.count("Access grant recorded") == 2


def test_new_account_with_valid_password_is_created(cli_database, monkeypatch, capsys):
    monkeypatch.setattr(
        "backend.__main__.getpass.getpass", lambda _: "valid-new-password"
    )
    main(["create-user", "alice", "--role", "customer"])
    with cli_database.connect() as connection:
        row = connection.execute(
            "SELECT password_hash FROM users WHERE username='alice'"
        ).fetchone()
        assert verify_password("valid-new-password", row["password_hash"])
    assert "Created account alice" in capsys.readouterr().out


def test_password_change_revokes_sessions_and_keeps_grants(
    cli_database, monkeypatch, capsys
):
    with cli_database.connect() as connection:
        connection.execute(
            "INSERT INTO sessions VALUES ('existing-token','customer','csrf','2099-01-01T00:00:00+00:00')"
        )
    monkeypatch.setattr(
        "backend.__main__.getpass.getpass", lambda _: "valid-changed-password"
    )
    main(["set-password", "customer"])
    with cli_database.connect() as connection:
        row = connection.execute(
            "SELECT password_hash FROM users WHERE username='customer'"
        ).fetchone()
        assert verify_password("valid-changed-password", row["password_hash"])
        assert not verify_password("test-password-only", row["password_hash"])
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id='customer'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute(
            "SELECT 1 FROM user_sites WHERE user_id='customer' AND site_id='north-01'"
        ).fetchone()
    assert "existing sessions revoked" in capsys.readouterr().out


def test_invalid_password_change_keeps_old_password_and_session(
    cli_database, monkeypatch, capsys
):
    with cli_database.connect() as connection:
        connection.execute(
            "INSERT INTO sessions VALUES ('existing-token','customer','csrf','2099-01-01T00:00:00+00:00')"
        )
    monkeypatch.setattr("backend.__main__.getpass.getpass", lambda _: "short")
    with pytest.raises(SystemExit):
        main(["set-password", "customer"])
    with cli_database.connect() as connection:
        row = connection.execute(
            "SELECT password_hash FROM users WHERE username='customer'"
        ).fetchone()
        assert verify_password("test-password-only", row["password_hash"])
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id='customer'"
            ).fetchone()[0]
            == 1
        )


def test_missing_reset_user_does_not_prompt(cli_database, monkeypatch, capsys):
    def unexpected_prompt(_):
        pytest.fail("Missing accounts should not prompt for a new password")

    monkeypatch.setattr("backend.__main__.getpass.getpass", unexpected_prompt)
    with pytest.raises(SystemExit):
        main(["set-password", "unknown-user"])
    assert "User not found" in capsys.readouterr().err
