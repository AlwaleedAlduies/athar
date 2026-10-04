from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'أمين المعرفة'
        USER = 'USER', 'مستكشف'
    role = models.CharField(max_length=5, choices=Role.choices, default=Role.USER)

    @property
    def is_admin(self):
        return self.is_active and (self.role == self.Role.ADMIN or self.is_superuser)


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.CharField('نبذة', max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Bookmark(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    entity = models.ForeignKey('history.Entity', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'entity'], name='unique_bookmark')]
        ordering = ['-created_at']


class ExplorationHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    entity = models.ForeignKey('history.Entity', on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'entity'], name='unique_visit')]
        ordering = ['-viewed_at']


class SearchHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    query = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
