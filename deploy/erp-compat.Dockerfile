FROM maven:3.9.11-eclipse-temurin-21-alpine AS build

WORKDIR /build
COPY apps/erp-compat/server/pom.xml ./pom.xml
COPY apps/erp-compat/server/src ./src
RUN mvn -DskipTests package

FROM eclipse-temurin:21-jre-alpine

RUN apk add --no-cache curl \
    && addgroup -S raj \
    && adduser -S -G raj raj

WORKDIR /app
COPY --from=build /build/target/erp-server-*.jar /app/erp-compat.jar
RUN mkdir -p /app/runtime/erp-compat \
    && chown -R raj:raj /app

USER raj

EXPOSE 8080

CMD ["java", "-jar", "/app/erp-compat.jar"]
