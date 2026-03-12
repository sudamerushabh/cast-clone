package org.springframework.samples.petclinic.owner;

import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/owners")
public class OwnerController {

    private final OwnerRepository ownerRepository;

    public OwnerController(OwnerRepository ownerRepository) {
        this.ownerRepository = ownerRepository;
    }

    @GetMapping
    public List<Owner> listOwners() {
        return ownerRepository.findAll();
    }

    @GetMapping("/{ownerId}")
    public Owner getOwner(@PathVariable int ownerId) {
        return ownerRepository.findById(ownerId)
                .orElseThrow(() -> new RuntimeException("Owner not found"));
    }

    @PostMapping
    public Owner createOwner(@RequestBody Owner owner) {
        return ownerRepository.save(owner);
    }

    @GetMapping("/search")
    public List<Owner> findByLastName(@RequestParam String lastName) {
        return ownerRepository.findByLastName(lastName);
    }
}
