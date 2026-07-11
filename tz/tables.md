User 
- id (pk)
- chat_id (unique)
- telegram_user_id (unique)
- created_at

Task
- id
- title
- description
- due_to
- due_to_has_time
- repeat_type
- repeat_interval
- status
- created_at
- user_id (FK → User)

Reminder
- id
- reminder_time
- sent_time
- reaction
- message_id
- task_id (FK → Task)

TaskEvent
- id
- task_id (FK → Task)
- event_type
- message_id (nullable)   # Telegram message_id; для undated_card_sent, evening_question_sent и т.п.
- created_at

index + uniq — в тикетах DB-01..DB-04 per model
