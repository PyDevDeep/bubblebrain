<?php
/**
 * Plugin Name: WooCommerce Bot Sales Tracker
 * Description: Відстеження продажів з Telegram-бота (digitaldreams). Зберігає UTM та session_id у куки і відправляє вебхук на бекенд.
 * Version: 1.0.0
 * Author: PyDevDeep
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit; // Exit if accessed directly
}

class BotSalesTracker {

    // ВКАЖІТЬ ТУТ URL ВАШОГО БЕКЕНДУ
    private $backend_webhook_url = 'https://YOUR_DOMAIN/api/v1/webhook/woo-order';

    public function __construct() {
        add_action( 'init', array( $this, 'capture_bot_lead' ) );
        add_action( 'woocommerce_checkout_update_order_meta', array( $this, 'save_bot_lead_to_order' ), 10, 2 );
        add_action( 'woocommerce_new_order', array( $this, 'notify_backend_of_order' ), 10, 2 );
    }

    public function capture_bot_lead() {
        if ( isset( $_GET['bot_source'] ) && isset( $_GET['bot_chat_id'] ) ) {
            $bot_chat_id = sanitize_text_field( $_GET['bot_chat_id'] );
            // Cookie на 30 днів
            setcookie( '_bot_lead_session_id', $bot_chat_id, time() + (30 * 24 * 60 * 60), '/' );
        }
    }

    /**
     * @param int $order_id
     * @param array $data
     */
    public function save_bot_lead_to_order( $order_id, $data ) {
        if ( isset( $_COOKIE['_bot_lead_session_id'] ) ) {
            $bot_chat_id = sanitize_text_field( $_COOKIE['_bot_lead_session_id'] );
            update_post_meta( $order_id, '_is_bot_lead', 'true' );
            update_post_meta( $order_id, '_bot_user_id', $bot_chat_id );
        }
    }

    /**
     * @param int $order_id
     * @param \WC_Order|bool $order
     */
    public function notify_backend_of_order( $order_id, $order ) {
        $is_bot_lead = get_post_meta( $order_id, '_is_bot_lead', true );

        if ( $is_bot_lead === 'true' ) {
            $bot_chat_id = get_post_meta( $order_id, '_bot_user_id', true );
            $order = wc_get_order( $order_id );

            if ( ! $order ) {
                return;
            }

            $payload = array(
                'order_id'   => $order_id,
                'session_id' => $bot_chat_id,
                'total'      => $order->get_total(),
                'currency'   => $order->get_currency(),
                'first_name' => $order->get_billing_first_name(),
                'last_name'  => $order->get_billing_last_name(),
                'phone'      => $order->get_billing_phone(),
                'items'      => array()
            );

            foreach ( $order->get_items() as $item_id => $item ) {
                $payload['items'][] = array(
                    'name'     => $item->get_name(),
                    'quantity' => $item->get_quantity(),
                    'total'    => $item->get_total()
                );
            }

            wp_remote_post( $this->backend_webhook_url, array(
                'method'      => 'POST',
                'timeout'     => 15,
                'headers'     => array(
                    'Content-Type' => 'application/json',
                ),
                'body'        => wp_json_encode( $payload ),
            ) );
        }
    }
}

new BotSalesTracker();
