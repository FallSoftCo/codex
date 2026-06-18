CREATE INDEX coordination_tasks_room_status_idx
    ON coordination_tasks (room, status, updated_at);
