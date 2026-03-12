package org.springframework.samples.petclinic.owner;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface OwnerRepository extends JpaRepository<Owner, Integer> {

    List<Owner> findByLastName(String lastName);

    @Query("SELECT o FROM Owner o WHERE o.city = :city")
    List<Owner> findByCity(String city);
}
