package com.rajads.erp.identity;

import com.rajads.erp.config.ErpProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "true")
public class BootstrapDataInitializer implements ApplicationRunner {
    private final PermissionRepository permissionRepository;
    private final RoleRepository roleRepository;
    private final AppUserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final ErpProperties properties;

    @Override
    @Transactional
    public void run(ApplicationArguments args) throws Exception {
        Files.createDirectories(Path.of(properties.storage().localPath()));
        Map<String, String> permissions = Map.ofEntries(
                Map.entry("OPERATOR_VIEW", "查看投放公司"), Map.entry("OPERATOR_MANAGE", "管理投放公司与投放线"),
                Map.entry("BALANCE_VIEW", "查看结余台账"), Map.entry("BALANCE_EDIT", "编辑草稿结余"),
                Map.entry("BALANCE_OVERRIDE", "覆盖自动计算值"), Map.entry("BALANCE_CONFIRM", "确认与重开结余"),
                Map.entry("IMPORT", "导入数据"), Map.entry("REPORT_VIEW", "查看报表"), Map.entry("REPORT_EXPORT", "导出报表"),
                Map.entry("USER_MANAGE", "管理用户与权限"), Map.entry("AUDIT_VIEW", "查看审计日志"),
                Map.entry("PERIOD_LOCK", "锁定与解锁期间"),
                Map.entry("REDEMPTION_VIEW", "查看充值领码活动"), Map.entry("REDEMPTION_MANAGE", "配置充值领码活动"),
                Map.entry("REDEMPTION_GENERATE", "生成远端兑换码"), Map.entry("REDEMPTION_EXPORT", "导出兑换码表"),
                Map.entry("REDEMPTION_REMOTE_MANAGE", "管理远端盘口连接")
        );
        List<Permission> permissionRecords = permissions.entrySet().stream()
                .map(entry -> permissionRepository.findByCode(entry.getKey())
                        .map(permission -> {
                            if (!entry.getValue().equals(permission.getName())) permission.setName(entry.getValue());
                            return permission;
                        })
                        .orElseGet(() -> new Permission(entry.getKey(), entry.getValue())))
                .toList();
        permissionRepository.saveAll(permissionRecords);

        Role superAdmin = roleRepository.findByCode("SUPER_ADMIN")
                .orElseGet(() -> roleRepository.save(new Role("SUPER_ADMIN", "超级管理员", "拥有所有功能和数据权限")));
        Role finance = roleRepository.findByCode("FINANCE_ADMIN")
                .orElseGet(() -> roleRepository.save(new Role("FINANCE_ADMIN", "财务管理员", "管理结余、导入和关账")));
        Role entry = roleRepository.findByCode("DATA_ENTRY")
                .orElseGet(() -> roleRepository.save(new Role("DATA_ENTRY", "录入员", "录入草稿和导入")));
        Role auditor = roleRepository.findByCode("AUDITOR")
                .orElseGet(() -> roleRepository.save(new Role("AUDITOR", "审计/只读", "查看报表和审计记录")));

        superAdmin.setPermissions(new LinkedHashSet<>(permissionRepository.findAll()));
        finance.setPermissions(new LinkedHashSet<>(permissionRepository.findAll().stream()
                .filter(permission -> !permission.getCode().equals("USER_MANAGE")).toList()));
        entry.setPermissions(findPermissions("OPERATOR_VIEW", "BALANCE_VIEW", "BALANCE_EDIT", "IMPORT", "REPORT_VIEW",
                "REDEMPTION_VIEW", "REDEMPTION_GENERATE", "REDEMPTION_EXPORT"));
        auditor.setPermissions(findPermissions("OPERATOR_VIEW", "BALANCE_VIEW", "REPORT_VIEW", "AUDIT_VIEW"));
        roleRepository.saveAll(List.of(superAdmin, finance, entry, auditor));

        if (userRepository.count() == 0) {
            AppUser admin = new AppUser();
            admin.setUsername(properties.bootstrapAdmin().username());
            admin.setDisplayName("开发管理员");
            admin.setPasswordHash(passwordEncoder.encode(properties.bootstrapAdmin().password()));
            admin.setEnabled(true);
            admin.setMustChangePassword(false);
            admin.setRoles(new LinkedHashSet<>(List.of(superAdmin)));
            userRepository.save(admin);
        }
    }

    private LinkedHashSet<Permission> findPermissions(String... codes) {
        LinkedHashSet<Permission> permissions = new LinkedHashSet<>();
        for (String code : codes) {
            permissions.add(permissionRepository.findByCode(code).orElseThrow());
        }
        return permissions;
    }
}
