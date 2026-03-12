package com.example;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

public class UserService {
    private final UserRepository userRepository;

    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public User findById(Long id) {
        return userRepository.findById(id);
    }

    public void createUser(String name, String email) {
        User user = new User(name, email);
        userRepository.save(user);
    }

    public String getUserNameById(Connection conn, Long id) throws Exception {
        PreparedStatement ps = conn.prepareStatement(
            "SELECT name FROM users WHERE id = ?"
        );
        ps.setLong(1, id);
        ResultSet rs = ps.executeQuery();
        if (rs.next()) {
            return rs.getString("name");
        }
        return null;
    }
}
