-- Preserve V7/V8 data while switching remote accounts from manually pasted tokens to password + TOTP login.
alter table redemption_remote_connections add column username varchar(120);
alter table redemption_remote_connections add column password_ciphertext text;
alter table redemption_remote_connections add column totp_secret_ciphertext text;
alter table redemption_remote_connections add column access_token_ciphertext text;
alter table redemption_remote_connections add column access_token_expires_at timestamp with time zone;
alter table redemption_remote_connections add column last_logged_in_at timestamp with time zone;

-- Historical account codes are the only guaranteed unique value. They are a temporary login-name placeholder
-- until an operator edits the account and supplies its real remote username, password and TOTP secret.
update redemption_remote_connections set username = code where username is null;
alter table redemption_remote_connections alter column username set not null;
alter table redemption_remote_connections add constraint uq_redemption_remote_connection_username unique (username);
alter table redemption_remote_connections alter column bearer_token_ciphertext drop not null;
