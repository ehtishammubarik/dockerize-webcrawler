## RUN scrapper with docker-compose 
## 
# Pre-requisites 
Install docker 
Install docker-compose 
Allow ports 6800 and 5432 in firewall 
go to project directory 
# Run following command
docker-compose up --build -d 

you can see logs of scrapper with command 
docker logs scrapper 
you can use this command to verify. 

curl http://localhost:6800/schedule.json -d project=immo_crawl -d spider=immoscout

Thank You. 
