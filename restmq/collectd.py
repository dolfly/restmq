# coding: utf-8

import os.path
import cyclone.web
import cyclone.redis

from twisted.python import log
from twisted.internet import defer

from restmq import core

import simplejson
import web

class CollectdRestQueueHandler(web.RestQueueHandler):

    @web.authorize("rest_producer")
    @defer.inlineCallbacks
    def post(self, queue):
        value = self.request.body
        if value is None:
            raise cyclone.web.HTTPError(400)
        if queue == 'data':
            queue = 'collectd_data'
            try:
                value = value.splitlines()
                value = list(map((lambda x: x.split(' ')[1:]),value))
                value = simplejson.dumps(value)
            except Exception, e:
                log.msg("ERROR: %s" % e)
                raise cyclone.web.HTTPError(503)
        elif queue == 'event':
            queue = 'collectd_event'
            try:
                value = value.splitlines()
                event = value.pop()
                value = list(map((lambda x: x.split(': ')),value[:-1]))
                value.append(['Event',event])
                value = simplejson.dumps(value)
            except Exception, e:
                log.msg("ERROR: %s" % e)
                raise cyclone.web.HTTPError(503)
        else:
            raise cyclone.web.HTTPError(400)
        callback = self.get_argument("callback", None)

        try:
            result = yield self.settings.oper.queue_add(queue, value)
        except Exception, e:
            log.msg("ERROR: oper.queue_add('%s', '%s') failed: %s" % (queue, value, e))
            raise cyclone.web.HTTPError(503)

        if result:
            self.settings.comet.queue.put(queue)
            web.CustomHandler(self, callback).finish(result)
        else:
            raise cyclone.web.HTTPError(400)

class Collectd(web.Application):

    def __init__(self, acl_file, redis_host, redis_port, redis_pool, redis_db):
        handlers = [
            (r"/",       web.IndexHandler),
            (r"/q/(.*)", web.RestQueueHandler),
            (r"/c/(.*)", web.CometQueueHandler),
            (r"/p/(.*)", web.PolicyQueueHandler),
            (r"/j/(.*)", web.JobQueueInfoHandler),
            (r"/stats/(.*)",  web.StatusHandler),
            (r"/queue",  web.QueueHandler),
            (r"/control/(.*)",  web.QueueControlHandler),
            (r"/ws/(.*)",  web.WebSocketQueueHandler),
        ]

        handlers.append((r"/collectd/(.*)", CollectdRestQueueHandler))

        try:
            acl = web.ACL(acl_file)
        except Exception, e:
            log.msg("ERROR: Cannot load ACL file: %s" % e)
            raise RuntimeError("Cannot load ACL file: %s" % e)

        db = cyclone.redis.lazyRedisConnectionPool(
            redis_host, redis_port,
            pool_size=redis_pool, db=redis_db)

        oper = core.RedisOperations(db)
        cwd = os.path.dirname(__file__)

        settings = {
            "db": db,
            "acl": acl,
            "oper": oper,
            "comet": web.CometDispatcher(oper),
            "static_path": os.path.join(cwd, "static"),
            "template_path": os.path.join(cwd, "templates"),
        }

        cyclone.web.Application.__init__(self, handlers, **settings)
