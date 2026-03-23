# On personal device with internet access
docker build -t video-router-dashboard .
docker save -o video-router-dashboard.tar video-router-dashboard
scp video-router-dashboard.tar root@172.17.___.___:/opt/video-router-dashboard/

# On the server
docker stop video-router-dashboard
docker rm video-router-dashboard
docker load -i /opt/video-router-dashboard/video-router-dashboard.tar
docker run -d \
  --name video-router-dashboard \
  --restart always \
  -p 8000:8000 \
  -e ROUTER_IP=172.17.___.___ \
  -e SSH_USER=root \
  -e SSH_PASSWORD=yourpassword \
  -e FLASK_PORT=8000 \
  video-router-dashboard