create table redemption_reward_tier_presets (
    remote_connection_id bigint primary key references redemption_remote_connections(id) on delete cascade,
    tiers_json text not null,
    tag_snapshot_json text not null,
    stale boolean not null default false,
    last_synced_at timestamp with time zone,
    saved_by bigint,
    saved_at timestamp with time zone not null default current_timestamp
);
