const express = require('express');
const app = express();

app.get('/api/users', (req, res) => {
    res.json([{ id: 1, name: 'Alice' }]);
});

app.post('/api/users', (req, res) => {
    res.status(201).json({ id: 2, name: req.body.name });
});

app.listen(3000, () => console.log('Listening on port 3000'));
