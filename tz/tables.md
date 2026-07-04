User 
- id (pk)
- chat_id 

Task
- id
- title
- description
- due_to
- repeat_type
- repeat_interval
- status
- created_at
- uid

Reminder
- id
- reminder_time
- sent_time
- reaction
- message_id
- task_id

TaskEvent
- task_id
- event_type
- created_at


index + uniq