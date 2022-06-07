from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import QuestionBank


@receiver(post_save, sender=QuestionBank)
def clear_shared_with(sender, instance, created, **kwargs):
    # if question bank is made public, clear the "shared_with" relationships
    if not instance.private:
        # mytodo: M2M not being updated in django admin!
        instance.shared_with.clear()
        print("shared_with list cleared")