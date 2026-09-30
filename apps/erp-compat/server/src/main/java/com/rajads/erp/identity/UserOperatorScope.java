package com.rajads.erp.identity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Entity
@Table(name = "user_operator_scopes")
@Getter
@Setter
@NoArgsConstructor
public class UserOperatorScope {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "operator_id")
    private Long operatorId;

    @Column(name = "all_operators", nullable = false)
    private boolean allOperators;

    public UserOperatorScope(Long userId, Long operatorId, boolean allOperators) {
        this.userId = userId;
        this.operatorId = operatorId;
        this.allOperators = allOperators;
    }
}
