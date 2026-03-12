package org.springframework.samples.petclinic.owner;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface OwnerRepository extends JpaRepository<Owner, Integer> {
    @Query("SELECT o FROM Owner o WHERE o.lastName LIKE :lastName%")
    List<Owner> findByLastName(@Param("lastName") String lastName);
}
