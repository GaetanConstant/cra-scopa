from sqlmodel import Session, select
from main import User, Project, engine, hash_password, create_db_and_tables

def seed():
    # Force recreate tables for the new link model
    create_db_and_tables()
    with Session(engine) as session:
        # Default password
        default_pwd = hash_password("scopa2024")
        
        users_to_add = [
            {"username": "gconstant", "full_name": "G. Constant", "email": "gconstant@scopa.co", "is_admin": True},
            {"username": "apatou", "full_name": "A. Patou", "email": "apatou@scopa.co", "is_admin": True},
            {"username": "nbrouet", "full_name": "N. Brouet", "email": "nbrouet@scopa.co", "is_admin": False},
            {"username": "jscallen", "full_name": "J. Scallen", "email": "jscallen@scopa.co", "is_admin": False},
            {"username": "oselcuk", "full_name": "O. Selcuk", "email": "oselcuk@scopa.co", "is_admin": False},
        ]

        for u_data in users_to_add:
            user = session.exec(select(User).where(User.username == u_data["username"])).first()
            if not user:
                user = User(
                    username=u_data["username"],
                    full_name=u_data["full_name"],
                    email=u_data["email"],
                    hashed_password=default_pwd,
                    is_admin=u_data["is_admin"]
                )
                session.add(user)
            else:
                user.is_admin = u_data["is_admin"]
                user.full_name = u_data["full_name"]
                user.hashed_password = default_pwd # Ensure we can log in for testing
                session.add(user)
        
        # Add some initial projects
        projects = [
            {"name": "SCOPA - INTERNE", "cat": "Mission"},
            {"name": "CLIENT DATA - PROJET A", "cat": "Mission"},
            {"name": "FORMATION IA", "cat": "Formation"},
            {"name": "APPRENTISSAGE SYMFONY", "cat": "Formation"}
        ]
        for p_data in projects:
            p = session.exec(select(Project).where(Project.name == p_data["name"])).first()
            if not p:
                p = Project(name=p_data["name"], category=p_data["cat"])
                session.add(p)
        
        session.commit()
        print("Seed terminé avec succès.")

if __name__ == "__main__":
    seed()
