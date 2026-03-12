package org.springframework.samples.petclinic.owner;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import java.util.List;

public interface OwnerRepository extends JpaRepository<Owner, Integer> {

    @Query("SELECT DISTINCT owner FROM Owner owner LEFT JOIN FETCH owner.pets WHERE owner.lastName LIKE :lastName%")
    List<Owner> findByLastName(@Param("lastName") String lastName);

    List<Owner> findByCity(String city);
}
