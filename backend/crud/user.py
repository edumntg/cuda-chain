from sqlalchemy.orm import Session
from models.user import User as UserModel # Alias to avoid confusion with schema
from schemas.user import UserCreate
from core.security import get_password_hash

def get_user_by_username(db: Session, username: str):
    return db.query(UserModel).filter(UserModel.username == username).first()

def create_user(db: Session, user: UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = UserModel(username=user.username, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user
