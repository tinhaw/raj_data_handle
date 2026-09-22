package com.rajads.erp.operator;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface OperatorRepository extends JpaRepository<Operator, Long> {
    boolean existsByCodeIgnoreCase(String code);
    Optional<Operator> findByCodeIgnoreCase(String code);
    Optional<Operator> findFirstByNameIgnoreCase(String name);
    List<Operator> findByIdIn(Collection<Long> ids);
    List<Operator> findByNameContainingIgnoreCaseOrCodeContainingIgnoreCase(String name, String code);
}
