package com.rajads.erp.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.identity.CompatibilityIdentityFilter;
import com.rajads.erp.shared.ApiError;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

import java.time.Instant;

@Configuration
@EnableMethodSecurity
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class CompatibilitySecurityConfig {
    @Bean
    SecurityFilterChain compatibilitySecurityFilterChain(
            HttpSecurity http,
            CompatibilityIdentityFilter identityFilter,
            ObjectMapper objectMapper) throws Exception {
        http
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(authorize -> authorize
                        .requestMatchers("/actuator/**", "/api-docs/**", "/swagger-ui/**", "/swagger-ui.html").permitAll()
                        .anyRequest().authenticated())
                .exceptionHandling(exceptions -> exceptions
                        .authenticationEntryPoint((request, response, exception) -> {
                            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
                            objectMapper.writeValue(response.getOutputStream(), new ApiError(
                                    "UNAUTHENTICATED", "请先登录", null, Instant.now(), java.util.Map.of()));
                        })
                        .accessDeniedHandler((request, response, exception) -> {
                            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
                            objectMapper.writeValue(response.getOutputStream(), new ApiError(
                                    "FORBIDDEN", "没有执行该操作的权限", null, Instant.now(), java.util.Map.of()));
                        }));
        http.addFilterBefore(identityFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }
}
