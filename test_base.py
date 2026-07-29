from src.models.base import MissionBaseModel

obj = MissionBaseModel()

print("ID:", obj.id)
print("Created:", obj.created_at)
print("Updated:", obj.updated_at)