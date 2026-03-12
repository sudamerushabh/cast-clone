package org.springframework.samples.petclinic.vet;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/vets")
public class VetController {
    @GetMapping
    public List<String> listVets() {
        return List.of("Dr. Smith", "Dr. Jones");
    }
}
