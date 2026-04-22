from rest_framework import viewsets

from posts.models import Author, Post, Tag
from posts.serializers import AuthorSerializer, PostSerializer, TagSerializer
from posts.tasks import notify_post_published


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer


class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all()
    serializer_class = PostSerializer

    def perform_create(self, serializer) -> None:
        post = serializer.save()
        if post.published:
            notify_post_published.delay(post.id)
