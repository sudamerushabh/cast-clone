from celery import shared_task

from posts.models import Post


@shared_task(queue="notifications")
def notify_post_published(post_id: int) -> str:
    post = Post.objects.get(pk=post_id)
    return f"notified subscribers about post #{post.id}: {post.title}"


@shared_task(queue="analytics")
def update_author_stats(author_id: int) -> dict[str, int]:
    from posts.models import Author
    author = Author.objects.get(pk=author_id)
    return {"author_id": author.id, "post_count": author.posts.count()}
