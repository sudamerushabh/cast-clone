CREATE TABLE IF NOT EXISTS vets (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(30),
    last_name VARCHAR(30)
);

CREATE TABLE IF NOT EXISTS types (
    id SERIAL PRIMARY KEY,
    name VARCHAR(80)
);

CREATE TABLE IF NOT EXISTS owners (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(30),
    last_name VARCHAR(30),
    address VARCHAR(255),
    city VARCHAR(80),
    telephone VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS pets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(30),
    birth_date DATE,
    type_id INT NOT NULL REFERENCES types(id),
    owner_id INT NOT NULL REFERENCES owners(id)
);

CREATE TABLE IF NOT EXISTS visits (
    id SERIAL PRIMARY KEY,
    pet_id INT NOT NULL REFERENCES pets(id),
    visit_date DATE,
    description VARCHAR(255)
);
