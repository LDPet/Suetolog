from datetime import date as Date

from reminder.models import Task


class TaskRepository:

    @staticmethod
    def create(user,
               title: str,
               description: str = "",
               due_to=None,
               due_to_has_time: bool = False,
               repeat_type: str | None = None,
               repeat_interval: int | None = None) -> Task:
        """Создать задачу с сохранением признака точного времени срока."""
        return Task.objects.create(
            user=user,
            title=title,
            description=description,
            due_to=due_to,
            due_to_has_time=due_to_has_time,
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
    def get_by_id_for_update(task_id: int) -> Task | None:
        try:
            return Task.objects.select_for_update().get(id=task_id)
        except Task.DoesNotExist:
            return None

    @staticmethod
    def get_active_by_user(user) -> list[Task]:
        return list(
            Task.objects.filter(user=user).filter(
                status=Task.Status.ACTIVE).order_by("-created_at"))

    @staticmethod
    def list_undated(user) -> list[Task]:
        return list(
            Task.objects.filter(
                user=user,
                status=Task.Status.ACTIVE,
                due_to__isnull=True,
            ).order_by("-created_at"))

    @staticmethod
    def list_for_day(user, date: Date) -> list[Task]:
        return list(
            Task.objects.filter(
                user=user,
                status=Task.Status.ACTIVE,
                due_to__date=date,
            ).order_by("due_to", "created_at"))

    @staticmethod
    def update_due_to(task: Task, due_to, due_to_has_time: bool) -> Task:
        """Одновременно обновить срок задачи и признак точного времени."""
        task.due_to = due_to
        task.due_to_has_time = due_to_has_time
        task.save(update_fields=["due_to", "due_to_has_time"])
        return task

    @staticmethod
    def update_status(task: Task, status: str) -> Task:
        task.status = status
        task.save(update_fields=["status"])
        return task

    @staticmethod
    def list_active_for_day(day: Date):
        return list(
            Task.objects.filter(
                status=Task.Status.ACTIVE,
                due_to__date=day,
            ).select_related("user").order_by("due_to", "created_at"))
