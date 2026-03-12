// tests/fixtures/csharp/SimpleClass.cs
using System;
using System.Collections.Generic;

namespace MyApp.Models
{
    public interface IEntity
    {
        int Id { get; set; }
    }

    public class BaseModel
    {
        public DateTime CreatedAt { get; set; }
    }

    [Serializable]
    public class User : BaseModel, IEntity
    {
        public int Id { get; set; }
        public string Name { get; set; }
        public string Email { get; set; }
        private List<string> _roles;

        public User(string name, string email)
        {
            Name = name;
            Email = email;
            _roles = new List<string>();
        }

        public void AddRole(string role)
        {
            _roles.Add(role);
        }

        public bool HasRole(string role)
        {
            return _roles.Contains(role);
        }
    }
}
