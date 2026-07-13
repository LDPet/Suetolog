from reminder.models import TaskEvent


class TaskEventRepository:

    @staticmethod
    def create(task, event_type: str, message_id: int = None) -> TaskEvent:
        return TaskEvent.objects.create(
            task=task,
            event_type=event_type,
            message_id=message_id,
        )

    @staticmethod
    def find_by_message_id(message_id: int) -> TaskEvent | None:
        try:
            return TaskEvent.objects.select_related("task").get(
                message_id=message_id)
        except TaskEvent.DoesNotExist:
            return None

    @staticmethod
    def find_by_event_type(event_type: str) -> list[TaskEvent]:
        return list(
            TaskEvent.objects.filter(
                event_type=event_type).order_by("-created_at"))
