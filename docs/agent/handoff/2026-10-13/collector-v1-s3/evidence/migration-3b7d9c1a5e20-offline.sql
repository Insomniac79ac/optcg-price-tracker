BEGIN;

-- Running upgrade 6c2242f6f439 -> 3b7d9c1a5e20

CREATE TABLE collection_entries (
    id SERIAL NOT NULL, 
    user_id INTEGER NOT NULL, 
    card_print_id INTEGER, 
    quantity INTEGER NOT NULL, 
    paid_jpy_per_card INTEGER, 
    acquired_on DATE, 
    note VARCHAR(500), 
    legacy_collection_item_id INTEGER, 
    legacy_card_id INTEGER, 
    resolution VARCHAR(16) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_collection_entries_user_print UNIQUE (user_id, card_print_id), 
    CONSTRAINT ck_collection_entries_quantity CHECK (quantity >= 1), 
    CONSTRAINT ck_collection_entries_paid CHECK (paid_jpy_per_card IS NULL OR paid_jpy_per_card >= 0), 
    CONSTRAINT ck_collection_entries_resolution CHECK (resolution IN ('exact', 'unresolved')), 
    CONSTRAINT ck_collection_entries_resolution_print CHECK ((resolution = 'exact') = (card_print_id IS NOT NULL)), 
    CONSTRAINT ck_collection_entries_note_length CHECK (note IS NULL OR length(note) <= 500), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    FOREIGN KEY(card_print_id) REFERENCES card_prints (id) ON DELETE RESTRICT
);

CREATE INDEX ix_collection_entries_user_id ON collection_entries (user_id);

CREATE INDEX ix_collection_entries_card_print_id ON collection_entries (card_print_id);

CREATE UNIQUE INDEX uq_collection_entries_legacy_item ON collection_entries (legacy_collection_item_id) WHERE legacy_collection_item_id IS NOT NULL;

CREATE TABLE collection_entry_events (
    id SERIAL NOT NULL, 
    user_id INTEGER NOT NULL, 
    card_print_id INTEGER NOT NULL, 
    quantity_before INTEGER NOT NULL, 
    quantity_after INTEGER NOT NULL, 
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_collection_entry_events_quantities CHECK (quantity_before >= 0 AND quantity_after >= 0 AND quantity_before <> quantity_after), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    FOREIGN KEY(card_print_id) REFERENCES card_prints (id) ON DELETE RESTRICT
);

CREATE INDEX ix_collection_entry_events_user_print_time ON collection_entry_events (user_id, card_print_id, occurred_at);

CREATE TABLE watchlist_entries (
    id SERIAL NOT NULL, 
    user_id INTEGER NOT NULL, 
    card_print_id INTEGER, 
    target_jpy INTEGER, 
    note VARCHAR(500), 
    legacy_wishlist_item_id INTEGER, 
    legacy_card_id INTEGER, 
    resolution VARCHAR(16) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_watchlist_entries_user_print UNIQUE (user_id, card_print_id), 
    CONSTRAINT ck_watchlist_entries_target CHECK (target_jpy IS NULL OR target_jpy > 0), 
    CONSTRAINT ck_watchlist_entries_resolution CHECK (resolution IN ('exact', 'unresolved')), 
    CONSTRAINT ck_watchlist_entries_resolution_print CHECK ((resolution = 'exact') = (card_print_id IS NOT NULL)), 
    CONSTRAINT ck_watchlist_entries_note_length CHECK (note IS NULL OR length(note) <= 500), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    FOREIGN KEY(card_print_id) REFERENCES card_prints (id) ON DELETE RESTRICT
);

CREATE INDEX ix_watchlist_entries_user_id ON watchlist_entries (user_id);

CREATE INDEX ix_watchlist_entries_card_print_id ON watchlist_entries (card_print_id);

CREATE UNIQUE INDEX uq_watchlist_entries_legacy_item ON watchlist_entries (legacy_wishlist_item_id) WHERE legacy_wishlist_item_id IS NOT NULL;

CREATE TABLE user_preferences (
    user_id INTEGER NOT NULL, 
    currency VARCHAR(3) DEFAULT 'JPY' NOT NULL, 
    collection_visibility VARCHAR(16) DEFAULT 'private' NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (user_id), 
    CONSTRAINT ck_user_preferences_currency CHECK (currency IN ('JPY')), 
    CONSTRAINT ck_user_preferences_visibility CHECK (collection_visibility IN ('private')), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE collection_value_points (
    user_id INTEGER NOT NULL, 
    point_date DATE NOT NULL, 
    methodology_version INTEGER NOT NULL, 
    value_jpy BIGINT, 
    priced_cards INTEGER NOT NULL, 
    total_cards INTEGER NOT NULL, 
    priced_entries INTEGER NOT NULL, 
    total_entries INTEGER NOT NULL, 
    prior_point_date DATE, 
    comparable_cards INTEGER, 
    prior_comparable_jpy BIGINT, 
    current_comparable_jpy BIGINT, 
    step_publishable BOOLEAN, 
    step_reason VARCHAR(64), 
    segment_number INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_collection_value_points PRIMARY KEY (user_id, point_date, methodology_version), 
    CONSTRAINT ck_collection_value_points_counts CHECK (priced_cards >= 0 AND priced_cards <= total_cards AND priced_entries >= 0 AND priced_entries <= total_entries), 
    CONSTRAINT ck_collection_value_points_value CHECK ((value_jpy IS NULL) = (priced_cards = 0) AND (value_jpy IS NULL OR value_jpy > 0)), 
    CONSTRAINT ck_collection_value_points_methodology CHECK (methodology_version > 0), 
    CONSTRAINT ck_collection_value_points_segment CHECK (segment_number >= 1), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='3b7d9c1a5e20' WHERE alembic_version.version_num = '6c2242f6f439';

COMMIT;

