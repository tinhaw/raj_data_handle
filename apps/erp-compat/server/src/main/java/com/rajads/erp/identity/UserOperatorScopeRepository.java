package com.rajads.erp.identity;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface UserOperatorScopeRepository extends JpaRepository<UserOperatorScope, Long> {
    List<UserOperatorScope> findByUserId(Long userId);
    void deleteByUserId(Long userId);
}
