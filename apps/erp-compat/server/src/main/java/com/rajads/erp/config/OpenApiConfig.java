package com.rajads.erp.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {
    @Bean
    OpenAPI erpOpenApi() {
        return new OpenAPI().info(new Info()
                .title("Raj Ads ERP API")
                .version("v1")
                .description("投放公司与投放线结余管理接口"));
    }
}
