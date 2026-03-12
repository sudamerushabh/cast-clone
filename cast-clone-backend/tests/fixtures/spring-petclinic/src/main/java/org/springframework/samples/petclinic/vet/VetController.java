package org.springframework.samples.petclinic.vet;

import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.GetMapping;
import java.util.List;
import java.util.Collections;

@RestController
@RequestMapping("/api/vets")
public class VetController {

    @GetMapping
    public List<String> listVets() {
        return Collections.emptyList();
    }
}
