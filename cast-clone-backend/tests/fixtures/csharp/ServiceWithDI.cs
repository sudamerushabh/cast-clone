// tests/fixtures/csharp/ServiceWithDI.cs
using System.Threading.Tasks;

namespace MyApp.Services
{
    public interface IUserRepository
    {
        Task<User> FindByIdAsync(int id);
        Task SaveAsync(User user);
    }

    public interface IEmailService
    {
        Task SendWelcomeEmail(string email);
    }

    public class UserService
    {
        private readonly IUserRepository _repo;
        private readonly IEmailService _emailService;

        public UserService(IUserRepository repo, IEmailService emailService)
        {
            _repo = repo;
            _emailService = emailService;
        }

        public async Task<User> GetUserAsync(int id)
        {
            var user = await _repo.FindByIdAsync(id);
            return user;
        }

        public async Task CreateUserAsync(string name, string email)
        {
            var user = new User(name, email);
            await _repo.SaveAsync(user);
            await _emailService.SendWelcomeEmail(email);
        }
    }
}
