from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
from schemas.user import UserCreate, User as UserSchema, Token, TokenData
from crud.user import get_user_by_username, create_user as crud_create_user
from core.security import create_access_token, verify_password, decode_access_token
from models.user import User as UserModel

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

@router.post("/register", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    created_user = crud_create_user(db=db, user=user)
    # Manually map to schema if not all fields are directly compatible or to exclude fields like hashed_password
    return UserSchema(id=created_user.id, username=created_user.username)


@router.post("/login", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = get_user_by_username(db, username=form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user.username} # "sub" is a standard claim for subject (the user)
    )
    return {"access_token": access_token, "token_type": "bearer"}

# Placeholder for a protected route example

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
    token_data = TokenData(username=username)

    user = get_user_by_username(db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user

@router.get("/users/me", response_model=UserSchema)
async def read_users_me(current_user: UserModel = Depends(get_current_user)): # We'll define get_current_user later
    return UserSchema(id=current_user.id, username=current_user.username)
