package db.migration;

import org.flywaydb.core.api.migration.BaseJavaMigration;
import org.flywaydb.core.api.migration.Context;

import java.sql.Connection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Standalone test fixture only; production DDL is owned by Alembic 0052. */
public class V29__redemption_shared_thresholds extends BaseJavaMigration {
    @Override
    public void migrate(Context context) throws Exception {
        Connection connection = context.getConnection();
        // V5 used an unnamed constraint. Find it by its exact column set so
        // both H2 and PostgreSQL fixtures work without changing old checksums.
        Map<String, Set<String>> constraints = new HashMap<>();
        try (var query = connection.prepareStatement("""
                select tc.constraint_name, kcu.column_name
                from information_schema.table_constraints tc
                join information_schema.key_column_usage kcu
                  on tc.constraint_catalog = kcu.constraint_catalog
                 and tc.constraint_schema = kcu.constraint_schema
                 and tc.constraint_name = kcu.constraint_name
                where tc.table_schema = current_schema
                  and tc.table_name = 'erp_compat_redemption_campaign_tiers'
                  and tc.constraint_type = 'UNIQUE'
                """); var rows = query.executeQuery()) {
            while (rows.next()) {
                constraints.computeIfAbsent(rows.getString(1), ignored -> new HashSet<>()).add(rows.getString(2));
            }
        }
        for (var entry : constraints.entrySet()) {
            if (entry.getValue().equals(Set.of("campaign_id", "min_deposit_amount"))) {
                String quotedName = "\"" + entry.getKey().replace("\"", "\"\"") + "\"";
                try (var statement = connection.createStatement()) {
                    statement.execute("alter table erp_compat_redemption_campaign_tiers drop constraint " + quotedName);
                }
            }
        }
    }
}
