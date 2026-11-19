import math
from heapq import heappush,heappop
FEATURES=('temperature','humidity','particles')
DISTANCE_SCALE=1_000_000
UNSERVED_COST=10**15

class _Network:
    def __init__(self,n):self.n=n;self.edges=[[] for _ in range(n)]
    def add(self,u,v,cap,cost):
        self.edges[u].append([v,cap,cost,len(self.edges[v]),0])
        self.edges[v].append([u,0,-cost,len(self.edges[u])-1,0])
        return len(self.edges[u])-1

def _min_cost_flow(net,source,sink,limit):
    n=net.n;potential=[0]*n;flow=0
    while flow<limit:
        dist=[None]*n;dist[source]=0;prev_node=[-1]*n;prev_edge=[-1]*n;heap=[(0,source)]
        while heap:
            d,u=heappop(heap)
            if dist[u]!=d:continue
            for index,edge in enumerate(net.edges[u]):
                v,cap,cost,_,_=edge
                if cap<=0:continue
                nd=d+cost+potential[u]-potential[v]
                if dist[v] is None or nd<dist[v]:
                    dist[v]=nd;prev_node[v]=u;prev_edge[v]=index;heappush(heap,(nd,v))
        if dist[sink] is None:break
        for v in range(n):
            if dist[v] is not None:potential[v]+=dist[v]
        add=limit-flow;v=sink
        while v!=source:
            add=min(add,net.edges[prev_node[v]][prev_edge[v]][1]);v=prev_node[v]
        v=sink
        while v!=source:
            edge=net.edges[prev_node[v]][prev_edge[v]]
            edge[1]-=add;edge[4]+=add
            reverse=net.edges[v][edge[3]];reverse[1]+=add;reverse[4]-=add
            v=prev_node[v]
        flow+=add
    return flow

def standardized_distance(values,center,mean,scale):
    total=0.0
    for index,feature in enumerate(FEATURES):
        if not scale[index]:raise ValueError('标准化尺度为0，无法计算距离')
        total+=((float(values[feature])-mean[index])/scale[index]-(float(center[feature])-mean[index])/scale[index])**2
    return math.sqrt(total)

def build_candidates(rows,clusters,mean,scale):
    if len(mean)!=len(FEATURES) or len(scale)!=len(FEATURES):raise ValueError('结果缺少标准化参数，无法计算到组中心的标准化距离')
    centers={int(c['cluster']):c['center'] for c in clusters}
    noise=[r for r in rows if int(r['cluster'])<0]
    if noise:centers[-1]={f:sum(float(r[f]) for r in noise)/len(noise) for f in FEATURES}
    groups={}
    for r in rows:
        try:cluster=int(r['cluster'])
        except (KeyError,TypeError,ValueError):raise ValueError('结果行缺少分区编号')
        if cluster not in centers:raise ValueError('结果缺少分区中心：'+str(cluster))
        if any(f not in r for f in FEATURES):raise ValueError('结果行缺少业务字段：'+str(r.get('reference','')))
        groups.setdefault(cluster,[]).append({'reference':r['reference'],'cluster':cluster,'kind':r.get('kind',''),'distance':standardized_distance(r,centers[cluster],mean,scale)})
    for candidates in groups.values():candidates.sort(key=lambda item:item['reference'])
    return groups,centers

def allowed_days(reference,days,availability):
    if reference in availability:return [day for day in days if day in set(availability[reference])]
    return list(days)

def solve_assignment(counts,groups,days,availability,remaining):
    days=list(days);requested={cluster:int(count) for cluster,count in counts.items() if int(count)>0}
    total=sum(requested.values())
    group_keys=sorted(requested)
    stations=[(cluster,item) for cluster in sorted(groups) if cluster in requested for item in groups[cluster]]
    station_index={(cluster,item['reference']):i for i,(cluster,item) in enumerate(stations)}
    station_base=1+len(group_keys);day_base=station_base+len(stations);sink=day_base+len(days)
    net=_Network(sink+1)
    source=0;group_node={cluster:1+i for i,cluster in enumerate(group_keys)}
    unserved={}
    for cluster in group_keys:
        net.add(source,group_node[cluster],requested[cluster],0)
        unserved[cluster]=net.add(group_node[cluster],sink,requested[cluster],UNSERVED_COST)
    station_edges={};day_edges={}
    for cluster,item in stations:
        node=station_base+station_index[(cluster,item['reference'])]
        station_edges[(cluster,item['reference'])]=net.add(group_node[cluster],node,1,int(round(item['distance']*DISTANCE_SCALE)))
        for day in allowed_days(item['reference'],days,availability):
            day_edges[(cluster,item['reference'],day)]=net.add(node,day_base+days.index(day),1,0)
    for index,day in enumerate(days):
        net.add(day_base+index,sink,max(0,int(remaining.get(day,0))),0)
    _min_cost_flow(net,source,sink,total)
    items=[]
    for cluster,item in stations:
        edge=net.edges[group_node[cluster]][station_edges[(cluster,item['reference'])]]
        if edge[4]<=0:continue
        for day in allowed_days(item['reference'],days,availability):
            day_edge=net.edges[station_base+station_index[(cluster,item['reference'])]][day_edges[(cluster,item['reference'],day)]]
            if day_edge[4]>0:
                items.append({'reference':item['reference'],'cluster':cluster,'kind':item['kind'],'distance':item['distance'],'day':day});break
    missing={cluster:net.edges[group_node[cluster]][unserved[cluster]][4] for cluster in group_keys}
    items.sort(key=lambda item:(item['day'],item['cluster'],item['reference']))
    return {'items':items,'missing':missing,'total_distance':sum(item['distance'] for item in items),'requested':requested}

def suggest_counts(groups,total):
    total=max(0,int(total));sizes={cluster:len(items) for cluster,items in groups.items()}
    population=sum(sizes.values())
    if not total or not population:return {str(cluster):0 for cluster in sorted(sizes)}
    exact={cluster:sizes[cluster]*total/population for cluster in sizes}
    counts={cluster:min(sizes[cluster],int(exact[cluster])) for cluster in sizes}
    leftover=total-sum(counts.values())
    order=sorted((cluster for cluster in sizes if counts[cluster]<sizes[cluster]),key=lambda cluster:(-(exact[cluster]-counts[cluster]),sizes[cluster],cluster))
    index=0
    while leftover>0 and order:
        payload=order[index%len(order)];counts[payload]+=1;leftover-=1;index+=1
        order=[cluster for cluster in order if counts[cluster]<sizes[cluster]] or order
    return {str(cluster):counts[cluster] for cluster in sorted(counts)}

def group_eligible_counts(groups,days,availability,remaining=None):
    remaining=remaining or {day:1 for day in days}
    open_days={day for day in days if int(remaining.get(day,0))>0}
    return {cluster:sum(1 for item in groups[cluster] if open_days & set(allowed_days(item['reference'],days,availability))) for cluster in groups}
