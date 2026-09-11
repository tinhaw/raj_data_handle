FROM maven:3.9.11-eclipse-temurin-21 AS build
WORKDIR /workspace
COPY .mvn/settings.xml /root/.m2/settings.xml
COPY pom.xml ./
COPY src ./src
# Build only the artifacts used by this service. `dependency:go-offline` also
# resolves Maven reporting/site plugins that are irrelevant to the runtime
# image and makes a first build unnecessarily sensitive to repository latency.
RUN --mount=type=cache,target=/root/.m2/repository \
    mvn -B -q -s /root/.m2/settings.xml -Dmaven.test.skip=true package

FROM eclipse-temurin:21-jre-alpine
RUN apk add --no-cache wget && addgroup -S erp && adduser -S erp -G erp
WORKDIR /app
COPY --from=build /workspace/target/erp-server-*.jar /app/app.jar
RUN mkdir -p /var/lib/erp/files && chown -R erp:erp /app /var/lib/erp
USER erp
EXPOSE 8080
ENV ERP_STORAGE_LOCAL_PATH=/var/lib/erp/files
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
