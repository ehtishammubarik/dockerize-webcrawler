## Scrapyd webcrawlers with postgresql and docker 
## 
# Pre-requisites 
Install docker <br />
Install docker-compose <br />
Allow ports 6800 and 5432 in firewall <br />
go to project directory 
# Run following command to build and run the application
```
docker-compose up --build -d 
```

# This will take some time after which you can go to localhost:5601 and access kibana dashboard


     Go to Discover tab on Kibana you'll be able to see the application logs there.




```
curl http://localhost:6800/schedule.json -d project=immo_crawl -d spider=immoscout

```

Thank You.
