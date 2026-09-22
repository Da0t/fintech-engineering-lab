import java.io.*;
import java.util.*;

/** Single-symbol, single-account exchange simulator. All money is integer cents.
 * Price/time FIFO matching, conservative buying-power reservation, deterministic
 * liquidity generation, and an accepted-command log for state reconstruction.
 */
public final class MarketEngine {
    static final long START_CASH = 10_000_000;
    static final long START_POSITION = 100;
    static final int MAX_ORDERS = 500;
    static final int MAX_TICKS = 5000;

    static final class Order {
        String id, side, type;
        long price, remaining, quantity, sequence;
        boolean user;
        Order(String id, String side, String type, long price, long qty, long seq, boolean user) {
            this.id=id; this.side=side; this.type=type; this.price=price;
            this.remaining=qty; this.quantity=qty; this.sequence=seq; this.user=user;
        }
    }

    static final class Engine {
        final NavigableMap<Long, ArrayDeque<Order>> bids = new TreeMap<>(Comparator.reverseOrder());
        final NavigableMap<Long, ArrayDeque<Order>> asks = new TreeMap<>();
        final LinkedHashMap<String, Order> userOrders = new LinkedHashMap<>();
        final Map<String, String> requests = new HashMap<>();
        final List<Map<String,Object>> fills = new ArrayList<>();
        final List<Map<String,Object>> prices = new ArrayList<>();
        final List<Map<String,Object>> events = new ArrayList<>();
        long cash=START_CASH, position=START_POSITION, sequence=0, mid=10000, fees=0;
        int tick=0, feedTick=0;
        boolean connected=true;
        final String liquidity;

        Engine(String liquidity) {
            require(Set.of("liquid", "thin").contains(liquidity), "Choose liquid or thin liquidity");
            this.liquidity=liquidity;
            refresh();
            prices.add(map("tick",0,"price",mid));
        }

        long reservedCash() {
            return userOrders.values().stream().filter(o -> o.side.equals("buy") && o.remaining>0)
                .mapToLong(o -> o.remaining*(o.price+fee(o.price))).sum();
        }
        long reservedPosition() {
            return userOrders.values().stream().filter(o -> o.side.equals("sell") && o.remaining>0)
                .mapToLong(o -> o.remaining).sum();
        }
        static long fee(long notional) { return (notional+999)/1000; } // 10 basis points, rounded up per fill

        void event(String type, String detail) {
            events.add(map("tick",tick,"type",type,"detail",detail));
        }

        void add(Order order) {
            (order.side.equals("buy") ? bids : asks).computeIfAbsent(order.price, k -> new ArrayDeque<>()).add(order);
        }

        boolean crosses(Order incoming, long price) {
            return incoming.type.equals("market") || (incoming.side.equals("buy") ? incoming.price>=price : incoming.price<=price);
        }

        void match(Order incoming) {
            var opposite = incoming.side.equals("buy") ? asks : bids;
            while(incoming.remaining>0 && !opposite.isEmpty() && crosses(incoming, opposite.firstKey())) {
                var level = opposite.firstEntry();
                Order resting = level.getValue().peek();
                if (incoming.user && resting.user) throw new IllegalStateException("Self-trade escaped preflight");
                long qty = Math.min(incoming.remaining, resting.remaining);
                long price = resting.price, notional=qty*price;
                incoming.remaining-=qty;
                resting.remaining-=qty;
                if(incoming.user || resting.user) {
                    Order user = incoming.user ? incoming : resting;
                    long charge=fee(notional);
                    if(user.side.equals("buy")) { cash-=notional+charge; position+=qty; }
                    else { cash+=notional-charge; position-=qty; }
                    fees+=charge;
                    fills.add(map("id", "fill-"+(fills.size()+1), "order_id",user.id,"side",user.side,
                        "quantity",qty,"price",price,"fee",charge,"tick",tick,
                        "liquidity",incoming.user ? "taker" : "maker"));
                }
                if(resting.remaining==0) level.getValue().remove();
                if(level.getValue().isEmpty()) opposite.pollFirstEntry();
            }
            if(incoming.remaining>0 && incoming.type.equals("limit")) add(incoming);
        }

        void removeExternal(NavigableMap<Long,ArrayDeque<Order>> book) {
            var iterator=book.entrySet().iterator();
            while(iterator.hasNext()) {
                var entry=iterator.next();
                entry.getValue().removeIf(o -> !o.user);
                if(entry.getValue().isEmpty()) iterator.remove();
            }
        }

        void refresh() {
            removeExternal(bids); removeExternal(asks);
            for(int level=0;level<8;level++) {
                long distance=liquidity.equals("thin") ? 5+level*17 : 2+level*2;
                long qty=liquidity.equals("thin") ? 4+(tick+level)%5 : 150+(tick*17+level*37)%150;
                match(new Order("mm-b-"+tick+"-"+level,"buy","limit",mid-distance,qty,++sequence,false));
                match(new Order("mm-a-"+tick+"-"+level,"sell","limit",mid+distance,qty,++sequence,false));
            }
            feedTick=tick;
        }

        Map<String,Object> order(String id, String side, String type, long qty, long limit) {
            require(id.matches("[A-Za-z0-9_-]{1,64}"), "Order ID must be 1–64 letters, digits, underscores or hyphens");
            String request=String.join("|",side,type,""+qty,""+limit);
            if(requests.containsKey(id)) {
                require(requests.get(id).equals(request), "Order ID reused with a different payload");
                return map("duplicate",true,"order_id",id);
            }
            require(connected, "Feed is disconnected. Reconnect before submitting orders.");
            require(userOrders.size()<MAX_ORDERS, "Session order limit reached; start a new session");
            require(Set.of("buy","sell").contains(side), "Side must be buy or sell");
            require(Set.of("market","limit").contains(type), "Type must be market or limit");
            require(qty>0 && qty<=10000, "Quantity must be between 1 and 10,000 whole shares");
            require(!type.equals("limit") || (limit>0 && limit<=1_000_000), "Limit price must be between 1 and 1,000,000 cents");
            Order incoming=new Order(id,side,type,limit,qty,sequence+1,true);
            var opposite=side.equals("buy") ? asks : bids;
            long remaining=qty, cost=0;
            for(var level:opposite.entrySet()) {
                if(remaining==0 || !crosses(incoming,level.getKey())) break;
                for(Order resting:level.getValue()) {
                    if(remaining==0) break;
                    require(!resting.user, "Order would self-trade with a resting order; cancel it first");
                    long take=Math.min(remaining,resting.remaining), value=take*resting.price;
                    cost+=value+fee(value); remaining-=take;
                }
            }
            if(side.equals("buy")) {
                long needed=type.equals("limit") ? qty*(limit+fee(limit)) : cost;
                require(cash-reservedCash()>=needed, "Insufficient available buying power");
            } else require(position-reservedPosition()>=qty, "Insufficient available shares; short selling is disabled");
            Long arrivalMid=(!bids.isEmpty() && !asks.isEmpty()) ? (bids.firstKey()+asks.firstKey())/2 : null;
            Long arrivalBest=opposite.isEmpty() ? null : opposite.firstKey();
            sequence++;
            int before=fills.size();
            userOrders.put(id,incoming);
            requests.put(id,request);
            match(incoming);
            long unfilled=incoming.remaining;
            if(type.equals("market")) incoming.remaining=0; // unfilled market quantity is cancelled, never rests
            event("order accepted",side+" "+qty+" shares · "+type+" · "+id);
            return map("duplicate",false,"order_id",id,"requested",qty,
                "filled",qty-unfilled,"unfilled",unfilled,"reference_mid",arrivalMid,"reference_best",arrivalBest,
                "fills",new ArrayList<>(fills.subList(before,fills.size())));
        }

        Map<String,Object> execute(String line) {
            String[] p=line.split("\\t",-1);
            switch(p[0]) {
                case "STEP": {
                    int count=Integer.parseInt(p[1]);
                    require(count>0 && count<=100 && tick+count<=MAX_TICKS, "Advance 1–100 ticks, up to 5,000 per session");
                    for(int i=0;i<count;i++) {
                        tick++;
                        // Deterministic synthetic price path, independent of wall clock and user orders.
                        mid=10000+Math.round(35*Math.sin(tick*.21)+18*Math.sin(tick*.73));
                        prices.add(map("tick",tick,"price",mid));
                        if(connected) refresh();
                    }
                    return map("advanced",count);
                }
                case "ORDER": return order(p[1],p[2],p[3],Long.parseLong(p[4]),Long.parseLong(p[5]));
                case "CANCEL": {
                    Order order=userOrders.get(p[1]);
                    require(order!=null && order.remaining>0,"Order is not open");
                    var book=order.side.equals("buy") ? bids : asks;
                    var queue=book.get(order.price); queue.remove(order);
                    if(queue.isEmpty()) book.remove(order.price);
                    order.remaining=0;
                    event("order cancelled",order.id+" · reserved funds released");
                    return map("cancelled",order.id);
                }
                case "DISCONNECT": connected=false; event("feed disconnected","Order entry blocked until a fresh snapshot arrives"); return map("connected",false);
                case "RECONNECT": {
                    int gap=tick-feedTick;
                    connected=true; refresh();
                    event("feed recovered","Applied fresh snapshot after "+gap+" missed synthetic ticks; resting orders matched against current liquidity");
                    return map("connected",true,"gap",gap);
                }
                default: throw new IllegalArgumentException("Unknown command");
            }
        }

        List<Map<String,Object>> depth(NavigableMap<Long,ArrayDeque<Order>> book) {
            List<Map<String,Object>> result=new ArrayList<>();
            for(var level:book.entrySet()) result.add(map("price",level.getKey(),"quantity",level.getValue().stream().mapToLong(o->o.remaining).sum(),
                "user_quantity",level.getValue().stream().filter(o->o.user).mapToLong(o->o.remaining).sum()));
            return result;
        }

        Map<String,Object> snapshot() {
            List<Map<String,Object>> orders=new ArrayList<>();
            for(Order o:userOrders.values()) if(o.remaining>0) orders.add(map("id",o.id,"side",o.side,"price",o.price,"quantity",o.quantity,"remaining",o.remaining));
            long expectedCash=START_CASH, expectedPosition=START_POSITION;
            for(var f:fills) {
                long qty=((Number)f.get("quantity")).longValue(), price=((Number)f.get("price")).longValue(), charge=((Number)f.get("fee")).longValue();
                boolean buy=f.get("side").equals("buy");
                expectedCash+=(buy ? -qty*price : qty*price)-charge;
                expectedPosition+=buy ? qty : -qty;
            }
            return map("symbol","NOVA","liquidity",liquidity,"tick",tick,"feed_tick",feedTick,"connected",connected,
                "mid",mid,"cash",cash,"reserved_cash",reservedCash(),"available_cash",cash-reservedCash(),
                "position",position,"available_position",position-reservedPosition(),"fees",fees,
                "bids",depth(bids),"asks",depth(asks),"orders",orders,"fills",fills,"prices",prices,"events",events,
                "checks",map("cash_reconciled",cash==expectedCash,"position_reconciled",position==expectedPosition,
                    "nonnegative_buying_power",cash-reservedCash()>=0,"no_overselling",position-reservedPosition()>=0,
                    "uncrossed_book",bids.isEmpty() || asks.isEmpty() || bids.firstKey()<asks.firstKey()));
        }
    }

    static void require(boolean test,String message) { if(!test) throw new IllegalArgumentException(message); }
    static Map<String,Object> map(Object... values) {
        var result=new LinkedHashMap<String,Object>();
        for(int i=0;i<values.length;i+=2) result.put((String)values[i],values[i+1]);
        return result;
    }
    static String json(Object value) {
        if(value==null) return "null";
        if(value instanceof String s) return "\""+s.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r").replace("\t","\\t")+"\"";
        if(value instanceof Number || value instanceof Boolean) return value.toString();
        if(value instanceof Map<?,?> m) {
            var parts=new ArrayList<String>(); for(var entry:m.entrySet()) parts.add(json(entry.getKey())+":"+json(entry.getValue()));
            return "{"+String.join(",",parts)+"}";
        }
        if(value instanceof Iterable<?> list) {
            var parts=new ArrayList<String>(); for(var item:list) parts.add(json(item)); return "["+String.join(",",parts)+"]";
        }
        throw new IllegalArgumentException("Unsupported JSON value");
    }

    public static void main(String[] args) throws Exception {
        var reader=new BufferedReader(new InputStreamReader(System.in));
        boolean batch=args.length>0 && args[0].equals("--batch");
        int remaining=0;
        if(batch) {
            var lines=reader.lines().toList();
            remaining=lines.size();
            reader=new BufferedReader(new StringReader(String.join("\n",lines)));
        }
        Engine engine=new Engine("liquid");
        var history=new ArrayList<String>();
        String line;
        while((line=reader.readLine())!=null) {
            remaining--;
            try {
                Map<String,Object> result=map();
                long started=System.nanoTime();
                if(line.startsWith("RESET\t")) {
                    engine=new Engine(line.split("\\t",-1)[1]); history.clear();
                } else if(line.equals("REPLAY")) {
                    String before=json(engine.snapshot());
                    Engine rebuilt=new Engine(engine.liquidity);
                    for(String command:history) rebuilt.execute(command);
                    boolean identical=before.equals(json(rebuilt.snapshot()));
                    require(identical,"Replay state diverged");
                    engine=rebuilt;
                    result=map("identical",true,"commands_replayed",history.size());
                } else if(!line.equals("STATE")) {
                    result=engine.execute(line);
                    history.add(line);
                }
                long nanos=System.nanoTime()-started;
                if(!batch || remaining==0) System.out.println(json(map("state",engine.snapshot(),"result",result,"engine_micros",nanos/1000.0,"commands",history.size())));
            } catch(Exception exc) {
                System.out.println(json(map("error",exc.getMessage()==null ? "Invalid command" : exc.getMessage())));
                if(batch) return;
            }
            System.out.flush();
        }
    }
}
