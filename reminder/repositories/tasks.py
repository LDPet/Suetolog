from reminder.models import Task


class TaskRepository:

    @staticmethod
    def create(user,
               title: str,
               description: str = "",
               due_to=None,
               repeat_type: str = "",
               repeat_interval: int | None = None) -> Task:
        return Task.objects.create(
            user=user,
            title=title,
            description=description,
            due_to=due_to,
            repeat_type=repeat_type,
            repeat_interval=repeat_interval,
        )

    @staticmethod
    def get_by_id(task_id: int) -> Task | None:
        try:
            return Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            return None

    @staticmethod
    def get_active_by_user(user) -> list[Task]:
        return list(
            Task.objects.filter(user=user).filter(
                status=Task.Status.ACTIVE).order_by("-created_at"))

    # Другие методы появятся в CORE-03
