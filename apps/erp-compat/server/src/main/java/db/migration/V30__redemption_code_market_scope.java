package db.migration;

import org.flywaydb.core.api.migration.BaseJavaMigration;
import org.flywaydb.core.api.migration.Context;

import java.sql.Connection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Standalone fixture only; production DDL is owned by Alembic 0053. */
public class V30__redemption_code_market_scope extends BaseJavaMigration {
    @Override
    public void migrate(Context context) throws Exception {
        var connection = context.getConnection();
        try (var sql = connection.createStatement()) {
            sql.execute("alter table erp_compat_redemption_issue_codes add remote_market_id bigint");
            sql.execute("""
                    update erp_compat_redemption_issue_codes code set remote_market_id = (
                        select issue.remote_market_id from erp_compat_redemption_code_issues issue where issue.id=code.issue_id)
                    """);
        }
        dropSingleColumnUnique(connection, "erp_compat_redemption_code_issues", "redemption_code");
        dropSingleColumnUnique(connection, "erp_compat_redemption_issue_codes", "code");
        try (var sql = connection.createStatement()) {
            sql.execute("alter table erp_compat_redemption_code_issues add constraint uq_erp_compat_issue_market_code unique(remote_market_id,redemption_code)");
            sql.execute("alter table erp_compat_redemption_code_issues add constraint uq_erp_compat_issue_id_market unique(id,remote_market_id)");
            sql.execute("alter table erp_compat_redemption_issue_codes alter column remote_market_id set not null");
            sql.execute("alter table erp_compat_redemption_issue_codes add constraint uq_erp_compat_issue_codes_market_code unique(remote_market_id,code)");
            sql.execute("alter table erp_compat_redemption_issue_codes add constraint ck_erp_compat_code_market_nonnegative check(remote_market_id>=0)");
            sql.execute("alter table erp_compat_redemption_issue_codes add constraint fk_erp_compat_issue_codes_market foreign key(issue_id,remote_market_id) references erp_compat_redemption_code_issues(id,remote_market_id) on delete cascade");
        }
    }

    private void dropSingleColumnUnique(Connection connection, String table, String column) throws Exception {
        Map<String, Set<String>> constraints = new HashMap<>();
        try (var query = connection.prepareStatement("""
                select tc.constraint_name,kcu.column_name from information_schema.table_constraints tc
                join information_schema.key_column_usage kcu
                  on tc.constraint_catalog=kcu.constraint_catalog and tc.constraint_schema=kcu.constraint_schema
                 and tc.constraint_name=kcu.constraint_name
                where tc.table_schema=current_schema and tc.table_name=? and tc.constraint_type='UNIQUE'
                """)) {
            query.setString(1, table);
            try (var rows = query.executeQuery()) {
                while (rows.next()) constraints.computeIfAbsent(rows.getString(1), ignored -> new HashSet<>()).add(rows.getString(2));
            }
        }
        for (var constraint : constraints.entrySet()) {
            if (constraint.getValue().equals(Set.of(column))) {
                try (var sql = connection.createStatement()) {
                    sql.execute("alter table " + table + " drop constraint \"" + constraint.getKey().replace("\"", "\"\"") + "\"");
                }
            }
        }
    }
}
