// tests/fixtures/csharp/EfAndDi.cs — EF Core, DI, and property type_args
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using System.Collections.Generic;

namespace MyApp.Data
{
    public class Product
    {
        public long Id { get; set; }
        public string Name { get; set; }
        public decimal Price { get; set; }
        public Category Category { get; set; }
        public long CategoryId { get; set; }
        public ICollection<OrderItem> OrderItems { get; set; }
    }

    public class Category
    {
        public long Id { get; set; }
        public string Name { get; set; }
        public IList<Product> Products { get; set; }
    }

    public class OrderItem
    {
        public long Id { get; set; }
        public long ProductId { get; set; }
        public Product Product { get; set; }
    }

    public class AppDbContext : DbContext
    {
        public DbSet<Product> Products { get; set; }
        public DbSet<Category> Categories { get; set; }
        public DbSet<OrderItem> OrderItems { get; set; }
    }

    public interface IProductService
    {
        void DoStuff();
    }

    public class ProductService : IProductService
    {
        public void DoStuff() { }
    }

    public class ModuleInitializer
    {
        public void ConfigureServices(IServiceCollection services)
        {
            services.AddScoped<IProductService, ProductService>();
            services.AddTransient<AppDbContext>();
        }
    }
}
