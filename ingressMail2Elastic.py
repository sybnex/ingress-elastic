#!/usr/bin/env python
#-*- coding: utf-8 -*-

import sys, re, os
import email
import imaplib
import datetime, time, calendar, pytz
import ConfigParser
import commands
from elasticsearch import Elasticsearch

class ingressMail2Elastic():

  def __init__(self, elasticserver, elasticindex, mailserver, mailport, mailuser, mailpass, debug = False):
    # init elasticsearch
    try:
      self._elastic = Elasticsearch([elasticserver])
      self._elasticindex = elasticindex
    except:
      self._elastic = False

    # init mailserver
    try:
      self._mail    = imaplib.IMAP4_SSL(mailserver, mailport)
      self._mail.login(mailuser, mailpass)
    except Exception, x:
      self.log("Email server connect error: " + str(x))
      self._mail = False

    self.debug = debug
    self.error = False
    self.error_print = 0
    self.success_print = 0
    self.counter = 0
    self.tz_offset   = datetime.datetime.now().hour - datetime.datetime.utcnow().hour

  def log(self, text, error = False, reset = False, severity = "INFO"):
    logtime  = str(datetime.datetime.now()) + ": "
    if error: severity = "ERROR"            + ": "
    else:     severity = severity           + ": "
    print logtime + severity + str(text)
    if reset: commands.getstatusoutput("rmdir lock")
    return error

  def importer(self):
    # Check if we are logged in the mailserver
    if self._mail == False:
      return self.log("Could not connect to email server!", error = True, reset = True)

    # Set app status to running to avoid double runs
    if commands.getstatusoutput("mkdir lock")[0]:
      return self.log("Parser already running will stop here!", error = True, reset = False)
    else:
      self.log("Starting parser.")

    try:
      self._mail.select()
    except Exception, x:
      return self.log("Error on Email selection.", error = True, reset = True)
     
    # For next year index with year as string
    now   = datetime.datetime.now()
    year  = str(now.year)[2:]
    month = str(now.month).zfill(2)
    eindex = self._elasticindex + "-" + year + month
    self.log("Actual index name is: " + str(eindex))
    try:
      self._elastic.indices.create(index  = eindex,
                        body   = {
                                   "settings" : {
                                     "index" : {
                                       "number_of_shards"   : 2,
                                       "number_of_replicas" : 0
                                     }
                                   },
                                   "mappings" : {
                                     "alert": {
                                       "properties"   : {
                                         "Location"   : {"type": "geo_point"},
                                         "Hour"       : {"type": "integer"},
                                         "Weekday"    : {"type": "integer"},
                                         "ALevel"     : {"type": "integer"},
                                         "PLevel"     : {"type": "integer"},
                                         "Portalname" : {"type": "string", "index": "not_analyzed"}
                                       }
                                     }
                                   }
                                 },
                        ignore = 400)
    except Exception, x:
      return self.log("Error in Mapping " + str(x), error = True, reset = True)

    # Read mails from server     
    typ, data = self._mail.search(None, 'SUBJECT', "Ingress Damage Report")
     
    for num in data[0].split():
        rv, data   = self._mail.fetch(num, '(RFC822)')
        msg        = email.message_from_string(data[0][1])
        subject    = msg["subject"]
        date_tuple = email.utils.parsedate_tz(msg["Date"])
        summary = {}
        self.log("Incoming email subject: " + str(subject))
     
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                  body = part.get_payload(decode=True).decode(part.get_content_charset())
                except:
                  if part.get_content_charset() == "windows-874":
                    body = part.get_payload(decode=True).decode("ISO-8859-11")
                  else:
                    self.log("Unknown charset: " + part.get_content_charset() + " ... ignoring this message!")
                    continue
    
                start = body.find("Agent Name:")
                end   = body.find("Ingress - End Transmission")
                final = body[start:end-12]
     
                timestamp = datetime.datetime.utcfromtimestamp(email.utils.mktime_tz(date_tuple))
                error_fields = ""
     
                # Workaround for stupid timezone delta stuff
                hour = int(timestamp.time().hour) + int(self.tz_offset)
                if hour >= 24: hour = hour - 24
     
                try:
                    summary.update({"Date":       timestamp})
                    summary.update({"Hour":       int(hour)})
                    summary.update({"Weekday":    int(datetime.date(date_tuple[0], date_tuple[1], date_tuple[2]).timetuple()[6])})
     
                    try:
                      summary.update({"Enemie":     re.search("by (.*)"                 , subject).group(1).strip()})
                      summary.update({"Enemy":      re.search("by (.*)"                 , subject).group(1).strip()})
                    except:
                      error_fields += "Enemy "
                    try:
                      summary.update({"Agent":      re.search("^Agent Name:(.*)$"       , final, re.MULTILINE).group(1).strip()})
                    except:
                      error_fields += "Agent "
                    try:
                      summary.update({"AFaction":   re.search("^Faction:(.*)$"          , final, re.MULTILINE).group(1).strip()})
                    except:
                      error_fields += "AFaction "
                    try:
                      summary.update({"ALevel":     int(re.search("^Current Level:L(.*)$"   , final, re.MULTILINE).group(1).strip())})
                    except:
                      error_fields += "ALevel "
                    try:
                      portal = re.search("^Portal - (.*?)$", final, re.MULTILINE | re.UNICODE).group(1).strip()
                      summary.update({"Portal":     portal})
                      summary.update({"Portalname": portal})
                    except Exception, x:
                      try:
                        portal = re.search("Portal - (.*?)\]\\r$", final, re.MULTILINE | re.UNICODE).group(1).strip()
                        summary.update({"Portal":     portal})
                        summary.update({"Portalname": portal})
                      except:
                        temp = re.search("Portal - (.*?)$", final, re.MULTILINE | re.UNICODE)
                        if temp: log("DEBUG: " + temp.group(1).strip())
                        error_fields += "Portal "
                    try:
                      temp = re.search("STATUS:(.*?)Health:" , final, re.DOTALL).group(1).strip()
                      summary.update({"PLevel":     int(re.search("^Level (.*)$" , temp, re.MULTILINE).group(1).strip())})
                    except:
                      log("temp for PLevel is: " + temp)
                      error_fields += "PLevel "
                    try:
                      summary.update({"Health":     re.search("^Health: (.*)$"          , final, re.MULTILINE).group(1).strip()})
                    except:
                      error_fields += "Health "
                    try:
                      summary.update({"Owner":      re.search("^Owner: (.*)$"           , final, re.MULTILINE).group(1).strip()})
                    except:
                      error_fields += "Owner "
                    try:
                      summary.update({"Report":     re.search("DAMAGE:(.*?)STATUS:"     , final, re.DOTALL).group(1).strip()})
                    except:
                      error_fields += "Report "
                    try:
                      address = re.search("DAMAGE REPORT(.*?)Portal -", final, re.DOTALL).group(1).strip()
                      summary.update({"Address":    re.search("(.*)\n(.*)"              , address, re.DOTALL).group(2).strip()})
                    except:
                      error_fields += "Address "
     
                except Exception, x:
                    log("Unknown exception: " + str(x))
                else:
                    if error_fields:
                      self.error = True
                      if self.error_print < 1:
                        self.log("---------- START ERROR STACK ----------")
                        self.log("An error ocured on field: " + str(error_fields))
                        self.log(final.encode("utf-8"))
                        if self.debug: self.log(summary.encode("utf-8"))
                        self.log("---------- END   ERROR STACK ----------")
                        self.error_print += 1
                    else:
                      self.error = False
     
            elif part.get_content_type() == "text/html":
                try:
                  htmlbody = part.get_payload(decode=True).decode(part.get_content_charset())
                except:
                  htmlbody = part.get_payload(decode=True)
     
                try:
                  try:
                    summary.update({"Location": re.search("(.*?)ll=(.*?)&pll(.*?)", htmlbody).group(2)})
                  except:
                    summary.update({"Location": re.search("(.*?)ll=(.*?)&amp;pll(.*?)", htmlbody,re.UNICODE).group(2)})
                except Exception, x:
                    self.error = True
                    self.log("An error on GPS occured: " + str(x))
            else:
              continue
     
        if not self.error:
          self.counter += 1                            # increase counter for logging
          self.log(str(summary))
          self._elastic.index(index = eindex, doc_type = "alert", body = summary)
          self._mail.store(num, '+FLAGS', '\\Deleted') # Mark message as deleted
     
    if self.counter > 0:
      self.log("Parsed " + str(self.counter) + " mail(s).")
      self._mail.expunge()                             # Cleanup mail account
     
    commands.getstatusoutput("rmdir lock")
    self._mail.close()
    self._mail.logout()
     
    self.log("Actual hour is " + str(datetime.datetime.now().hour) + " so offset will be: " +str(self.tz_offset))
    self.log("Stopping parser.")

    return True     

if __name__ == '__main__':
  """
  Starts main class for the importing
  and stays forever in a loop
  """
  helptext  = "Usage: %s" % sys.argv[0]
  helptext += """

              Needed ENV variables:
                 ELASTICSERVER => Elasticsearch server @ port 9200
                 ELASTICINDEX  => Index for naming for month based index
                 MAILSERVER    => Mail server for email catching
                 MAILPORT      => IMAP Port to use
                 MAILUSER      => Mail user login name
                 MAILPASS      => Password for mail user
                 SLEEPTIMER    => Sleep between imports (default 60)
                 DEBUGMODE     => 0 or 1 / default: 0
              """
  try:
    mailserver    = os.environ['MAILSERVER'] 
    mailport      = os.environ['MAILPORT'] 
    mailuser      = os.environ['MAILUSER'] 
    mailpass      = os.environ['MAILPASS'] 
    elasticserver = os.environ['ELASTICSERVER'] 
    elasticindex  = os.environ['ELASTICINDEX'] 
  except:
    sys.exit(helptext)

  try:    sleeptimer = os.environ['SLEEPTIMER'] 
  except: sleeptimer = 60
  try:    
    if   os.environ['DEBUGMODE'] == str(1): debugmode = True 
    elif os.environ['DEBUGMODE'] == str(0): debugmode = False
    else:                                   debugmode = False
  except: 
    debugmode  = False

  if mailserver and mailport and mailuser and mailpass and elasticserver and elasticindex:
    while True:
      obj = ingressMail2Elastic(elasticserver, elasticindex, mailserver, mailport, mailuser, mailpass, debugmode)
      obj.importer()
      del obj
      time.sleep(float(sleeptimer))
  else:
    sys.exit(helptext)

