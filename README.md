# Automatic Assessment Platform (AASP)
This application is developed as part of my Final Year Project in Nanyang Technological University, Singapore.

This project includes enhancements - Concurrency question & MCQ assessment support, improved analytics and bug fixes.

## About

AASP is a web-based online assessment platform that allows educators to create and manage assessments for their
students. With test proctoring features, assessments can be administered remotely while enforcing a strict and monitored test environment.

The platform is built with the [Django Web Framework](https://djangoproject.com/) and
uses [Judge0](https://github.com/judge0/judge0) for code compilation and execution.

## Installation

### Local Development

1. Clone the repository, check out the `master` branch.
   ```bash
   # via http
   git clone https://github.com/LGWayneq/aasp-core
   
   # or via ssh (you need to add your ssh publickey to your github account)
   git clone git@github.com:LGWayneq/aasp-core.git
   ```

2. Make a copy of the `.env_dev` example file and save it as `.env`.
   ```shell
   cp ./config/.env_dev ./config/.env
   ```

3. Open `.env` and update the `SECRET_KEY` and `AASP_POSTGRES_PASSWORD` fields.

4. With docker-compose, create and start the containers:
   ```shell
   docker-compose -f docker-compose-dev.yml up -d
   ```

5. Open the project in your IDE, create a virtual environment and install the requirements.
   ```shell
   # unix/linux
   python3 -m venv venv
   source ./venv/bin/activate
   python3 -m pip install -r requirements.txt
   ```

6. Since this is the first launch, the database needs to be generated with Django, and pre-populated with an admin
   account.  
   Refer to [migration files](./core/migrations) for the default admin account credentials.
   ```shell
   python3 manage.py migrate
   ```

7. Run the development webserver. The site will be accessible at [http://localhost:8000/](http://localhost:8000/)
   ```shell
   python3 manage.py runserver
   ```

### Exporting Docker Images
```shell
docker save $(docker images --format '{{.Repository}}:{{.Tag}}') -o exported-images.tar
```

### Production

#### Initial Deployment

1. Clone the repository, check out the `master` branch. You may skip this step if you already have a copy of the repository (e.g. from an archive). 
   ```bash
   # via http
   git clone https://github.com/LGWayneq/aasp-core
   
   # or via ssh (you need to add your ssh publickey to your github account)
   git clone git@github.com:LGWayneq/aasp-core.git
   ```

2. Make a copy of the `.env_prod` example file and save it as `.env`.
   ```shell
   cp ./config/.env_prod ./config/.env
   ```

3. Open `.env` and update the `SECRET_KEY` and `AASP_POSTGRES_PASSWORD` fields.

4. If the machine is offline, you will need to load docker images from the `exported-images.tar` file (if available).
   ```shell
   sudo docker load -i exported-images.tar
   ```

5. With docker-compose, create and start the containers.
   ```shell
   sudo docker-compose -f docker-compose.yml up -d
   ```

6. Once the containers have been created and started, the site will be accessible at `http://<host-ip>/` (port 80)

#### Performing updates

Note: If changes were made to the database schema, make sure to commit the migration files as well.

1. Push your commits to remote.
2. On the server, pull the new changes and restart containers:
   ```shell
   git pull
   sudo docker-compose restart

   # create new containers if necessary
   sudo docker-compose -f docker-compose.yml up -d
   ```

## Initial Setup
### Default superuser account
By default, only a single `ADMIN` account with superuser privileges is created. The default password for this user is `password123`. 

### Creation of other accounts
To create an Educator account, create the user and add the user to the Educator group. The same applies for Lab Assistants.

For Student accounts, they are created on demand when students are enrolled into courses, so there is no need to pre-create these accounts. The initial password will be sent to each student email upon account creation.

Other user accounts can be created through the Django Admin Dashboard by logging in as the `ADMIN` account.

## Credits

### Project Contributors

| Contributor                                             | Period         | Links                                                                                                                                                                                                     |
|---------------------------------------------------------|----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [Lee Jun Wei](https://www.linkedin.com/in/leejunweisg/) | Jan - Dec 2022 | [Report](./documents/leejunwei/SCSE21-0804_report.pdf) [Slides](./documents/leejunwei/final-presentation-slides.pdf) [Poster](./documents/leejunwei/fyp-poster.pdf) [Video](https://youtu.be/T0sULC8Wh7k) |
| [Liu Wing Lam](https://www.linkedin.com/in/liuwinglam) | Aug 2022 - May 2023 | [Report](./documents/liuwinglam/SCSE22-0184_report.pdf) [Slides](./documents/liuwinglam/presentation-slides.pdf) |
| [Chua Chong Yih](https://www.linkedin.com/in/chuachongyih) | Jan - Dec 2023 | |
| [Liau G Wayne](https://www.linkedin.com/in/lgwayne1999) | Aug 2023 - May 2024 | |

### Others

- Bootstrap 5 Template from [mazer](https://github.com/zuramai/mazer)
- Face Detection library and model from [InsightFace](https://github.com/deepinsight/insightface)
