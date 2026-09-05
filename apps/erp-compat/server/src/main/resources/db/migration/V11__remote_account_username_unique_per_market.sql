-- Remote usernames are scoped to their market: the same operator account name
-- may legitimately exist on different remote backends.
alter table redemption_remote_connections drop constraint if exists uq_redemption_remote_connection_username;
alter table redemption_remote_connections add constraint uq_redemption_remote_connection_market_username
    unique (market_id, username);
