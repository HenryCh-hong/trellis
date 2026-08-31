from app.db.session import engine
from app.models import Base

Base.metadata.create_all(engine)
print("schema created")
