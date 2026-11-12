-- Preserve the original spelling of every pre-existing task.
ALTER TABLE erp_compat_redemption_code_batches
    ADD COLUMN special_code_naming VARCHAR(20) DEFAULT 'ORIGINAL' NOT NULL
    CONSTRAINT ck_erp_compat_batch_code_naming CHECK (special_code_naming IN ('ORIGINAL', 'TEN_K'));
