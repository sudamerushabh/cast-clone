from rest_framework.routers import DefaultRouter

from posts.views import AuthorViewSet, PostViewSet, TagViewSet

router = DefaultRouter()
router.register("authors", AuthorViewSet, basename="authors")
router.register("tags", TagViewSet, basename="tags")
router.register("posts", PostViewSet, basename="posts")

urlpatterns = router.urls
